from __future__ import annotations

import html
import time
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "photo_component" / "index.html"

PARENT_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><style>html,body{margin:0;width:100%;}iframe{display:block;width:100%;height:1400px;border:0;}</style></head>
<body><iframe id="component" src="/component.html"></iframe>
<script>
window.testEvents=[];
window.serverPhotos=new Map();
window.removedIds=[];
window.mode='save';
window.delayedTimers=[];
const frame=()=>document.getElementById('component').contentWindow;
function selectionsIntoState(selections){
  (selections||[]).forEach(s=>{
    if(!window.serverPhotos.has(s.photo_id) && !window.removedIds.includes(s.photo_id)){
      window.serverPhotos.set(s.photo_id,{photo_id:s.photo_id,name:s.name,status:'pending',error:'',retryable:false,manual_required:false,preview:''});
    }
  });
}
function sendRender(){
  frame().postMessage({type:'streamlit:render',args:{
    photos:[...window.serverPhotos.values()], removed_ids:[...window.removedIds], disabled:false,
    retry_delays_ms:[1000,2000,4000]
  }},'*');
}
function record(v){
  window.testEvents.push({
    t:performance.now(), action:v.action||'', retry_kind:v.retry_kind||'',
    photo_id:(v.photo&&v.photo.photo_id)||v.photo_id||'', attempt:(v.photo&&v.photo.attempt)||v.attempt||0,
    name:(v.photo&&v.photo.name)||'', prepared_size:(v.photo&&v.photo.prepared_size)||0, width:(v.photo&&v.photo.width)||0, height:(v.photo&&v.photo.height)||0,
    client_failures:(v.client_failures||[]).map(x=>({photo_id:x.photo_id,retryable:x.retryable,error_code:x.error_code,attempt:x.attempt}))
  });
}
window.addEventListener('message',e=>{
  const m=e.data||{};
  if(m.type==='streamlit:componentReady'){ sendRender(); return; }
  if(m.type==='streamlit:setFrameHeight') return;
  if(m.type!=='streamlit:setComponentValue') return;
  const v=m.value||{}; record(v); selectionsIntoState(v.selections);
  if(v.action==='selection_started') { sendRender(); return; }
  if(v.action==='sync_failures') {
    (v.client_failures||[]).forEach(f=>window.serverPhotos.set(f.photo_id,{
      photo_id:f.photo_id,name:f.name||'photo.jpg',status:'failed',error:f.user_error||'Upload failed',
      retryable:!!f.retryable,manual_required:true,preview:''
    }));
    sendRender(); return;
  }
  if(v.action==='remove') {
    window.removedIds.push(v.photo_id); window.serverPhotos.delete(v.photo_id); sendRender(); return;
  }
  if(v.action==='upload' || v.action==='retry') {
    const p=v.photo; if(!p) return;
    const saved={photo_id:p.photo_id,name:p.name,status:'saved',error:'',retryable:false,manual_required:false,preview:''};
    const failed={photo_id:p.photo_id,name:p.name,status:'failed',error:'Upload failed',retryable:true,manual_required:false,preview:''};
    if(window.mode==='save') { window.serverPhotos.set(p.photo_id,saved); setTimeout(sendRender,20); return; }
    if(window.mode==='transient_then_save') {
      window.serverPhotos.set(p.photo_id, p.attempt>=4?saved:failed); setTimeout(sendRender,20); return;
    }
    if(window.mode==='permanent') {
      window.serverPhotos.set(p.photo_id,{...failed,retryable:false,manual_required:true,error:'This photo could not be prepared.'}); setTimeout(sendRender,20); return;
    }
    if(window.mode==='always_transient') { window.serverPhotos.set(p.photo_id,failed); setTimeout(sendRender,20); return; }
    if(window.mode==='manual_save') {
      window.serverPhotos.set(p.photo_id, v.retry_kind==='manual'?saved:failed); setTimeout(sendRender,20); return;
    }
    if(window.mode==='selective_transient') {
      const result=(p.name||'').startsWith('bad') && p.attempt<4 ? failed : saved;
      window.serverPhotos.set(p.photo_id,result); setTimeout(sendRender,20); return;
    }
    if(window.mode==='delayed_saved') {
      const timer=setTimeout(()=>{ window.serverPhotos.set(p.photo_id,saved); sendRender(); },900); window.delayedTimers.push(timer); return;
    }
  }
});
</script></body></html>'''


@pytest.fixture
def browser_page():
    component_html = html.escape(COMPONENT.read_text(encoding="utf-8"), quote=True)
    parent_html = PARENT_HTML.replace(
        '<iframe id="component" src="/component.html"></iframe>',
        f'<iframe id="component" srcdoc="{component_html}"></iframe>',
    )
    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if Path("/usr/bin/chromium").exists():
            launch_kwargs["executable_path"] = "/usr/bin/chromium"
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.set_content(parent_html, wait_until="load")
        frame = page.frame_locator("#component")
        frame.locator("#photo-input").wait_for(state="attached")
        try:
            yield page, frame
        finally:
            context.close()
            browser.close()


def make_jpeg(path: Path, size=(1200, 900), colour=(80, 120, 160), *, orientation=None, noise=False) -> Path:
    if noise:
        image = Image.effect_noise(size, 100).convert("RGB")
    else:
        image = Image.new("RGB", size, colour)
    exif = image.getexif()
    if orientation:
        exif[274] = orientation
    image.save(path, format="JPEG", quality=95, exif=exif)
    return path


def upload_events(page):
    return page.evaluate("window.testEvents.filter(e => e.action==='upload' || e.action==='retry')")


def test_three_photos_compress_and_hold_stable_two_column_mobile_layout(browser_page, tmp_path: Path):
    page, frame = browser_page
    large = make_jpeg(tmp_path / "large.jpg", size=(3600, 2800), noise=True)
    portrait = make_jpeg(tmp_path / "portrait.jpg", size=(1200, 1800), orientation=6)
    small = make_jpeg(tmp_path / "small.jpg", size=(1000, 700), colour=(120, 160, 200))
    assert large.stat().st_size > 5_000_000

    frame.locator("#photo-input").set_input_files([str(large), str(portrait), str(small)])
    frame.locator(".status.saved").nth(2).wait_for(timeout=30_000)

    events = upload_events(page)
    first_attempts = [e for e in events if e["attempt"] == 1]
    assert len(first_attempts) == 3
    assert all(e["prepared_size"] <= int(1.85 * 1024 * 1024) for e in first_attempts)
    assert all(max(e["width"], e["height"]) <= 1800 for e in first_attempts)
    portrait_event = next(e for e in first_attempts if e["name"] == "portrait.jpg")
    assert (portrait_event["width"], portrait_event["height"]) == (1800, 1200)  # EXIF orientation 6 applied

    cards = frame.locator(".card")
    boxes = [cards.nth(i).bounding_box() for i in range(3)]
    assert all(box is not None for box in boxes)
    assert abs(boxes[0]["y"] - boxes[1]["y"]) <= 2
    assert boxes[2]["y"] > boxes[0]["y"] + 20
    assert all(box["x"] + box["width"] <= 390 for box in boxes)
    assert max(box["height"] for box in boxes) - min(box["height"] for box in boxes) <= 2


def test_transient_failure_gets_exactly_three_automatic_retries_at_1_2_4_seconds(browser_page, tmp_path: Path):
    page, frame = browser_page
    page.evaluate("window.mode='transient_then_save'; window.testEvents=[]; window.serverPhotos=new Map(); window.removedIds=[];")
    photo = make_jpeg(tmp_path / "retry.jpg")
    frame.locator("#photo-input").set_input_files(str(photo))
    frame.locator(".status.saved").wait_for(timeout=20_000)

    events = upload_events(page)
    assert len(events) == 4  # initial + exactly three automatic retries
    assert [e["attempt"] for e in events] == [1, 2, 3, 4]
    deltas = [(events[i]["t"] - events[i-1]["t"]) / 1000 for i in range(1, 4)]
    assert deltas[0] >= 0.9
    assert deltas[1] >= 1.9
    assert deltas[2] >= 3.9


def test_permanent_server_rejection_is_not_automatically_retried(browser_page, tmp_path: Path):
    page, frame = browser_page
    page.evaluate("window.mode='permanent'; window.testEvents=[]; window.serverPhotos=new Map(); window.removedIds=[];")
    photo = make_jpeg(tmp_path / "permanent.jpg")
    frame.locator("#photo-input").set_input_files(str(photo))
    frame.locator(".status.failed").wait_for(timeout=10_000)
    time.sleep(4.5)
    assert len(upload_events(page)) == 1
    assert frame.get_by_role("button", name="Retry").count() == 0


def test_exhausted_transient_retries_show_manual_retry_and_only_failed_photo_retries(browser_page, tmp_path: Path):
    page, frame = browser_page
    page.evaluate("window.mode='always_transient'; window.testEvents=[]; window.serverPhotos=new Map(); window.removedIds=[];")
    photo = make_jpeg(tmp_path / "manual.jpg")
    frame.locator("#photo-input").set_input_files(str(photo))
    retry = frame.get_by_role("button", name="Retry")
    retry.wait_for(timeout=20_000)
    assert len(upload_events(page)) == 4

    page.evaluate("window.mode='manual_save'")
    retry.click()
    frame.locator(".status.saved").wait_for(timeout=10_000)
    events = upload_events(page)
    assert len(events) == 5
    assert events[-1]["retry_kind"] == "manual"


def test_successful_photo_is_not_reuploaded_when_another_photo_retries(browser_page, tmp_path: Path):
    page, frame = browser_page
    page.evaluate("window.mode='selective_transient'; window.testEvents=[]; window.serverPhotos=new Map(); window.removedIds=[];")
    good = make_jpeg(tmp_path / "good.jpg", colour=(60, 100, 140))
    bad = make_jpeg(tmp_path / "bad.jpg", colour=(140, 100, 60))
    frame.locator("#photo-input").set_input_files([str(good), str(bad)])
    frame.locator(".status.saved").nth(1).wait_for(timeout=20_000)

    events = upload_events(page)
    good_events = [e for e in events if e["name"] == "good.jpg"]
    bad_events = [e for e in events if e["name"] == "bad.jpg"]
    assert len(good_events) == 1
    assert [e["attempt"] for e in bad_events] == [1, 2, 3, 4]


def test_remove_during_upload_stays_removed_even_if_late_success_arrives(browser_page, tmp_path: Path):
    page, frame = browser_page
    page.evaluate("window.mode='delayed_saved'; window.testEvents=[]; window.serverPhotos=new Map(); window.removedIds=[];")
    photo = make_jpeg(tmp_path / "remove.jpg")
    frame.locator("#photo-input").set_input_files(str(photo))
    frame.locator(".status").filter(has_text="Uploading").wait_for(timeout=10_000)
    frame.get_by_role("button", name="Remove").click()
    time.sleep(1.3)
    assert frame.locator(".card").count() == 0
    actions = page.evaluate("window.testEvents.map(e => e.action)")
    assert "remove" in actions
