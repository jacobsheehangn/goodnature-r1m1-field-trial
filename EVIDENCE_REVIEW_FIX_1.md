# Evidence review — pipeline fix 1

The first evidence run correctly blocked release approval, but five browser tests stopped before reaching the app assertions.

## Findings

- Four failures used Playwright `.check()` on Streamlit's hidden radio input. Streamlit renders a visible label/control over that input, so Playwright correctly reported pointer interception. The tests now click the same visible label a person clicks.
- The Move trap test tried to click a closed mobile sidebar. The test now opens the drawer first.
- The gate report read counts from the outer `<testsuites>` node and incorrectly reported zero tests. It now aggregates the nested `<testsuite>` values.
- No app acceptance criteria were removed or weakened.
- The candidate remains unapproved until the corrected run completes and the generated screenshots are reviewed.
