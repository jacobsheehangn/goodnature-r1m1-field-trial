# Deploy R1/M1 Field Trial to Render

## Before starting

Create and verify:

1. A GitHub account using your work email.
2. Two-factor authentication on GitHub.
3. A Render account using your work email.
4. A strong shared pilot password stored in your password manager.

Do not put the app password in GitHub.

## 1. Create the GitHub repository

Create a **private** repository named:

`goodnature-r1m1-field-trial`

Do not initialise it with a README, licence or `.gitignore`, because this package already contains those files.

Upload the contents of this folder to the repository root.

The repository root should directly contain `app.py`, `render.yaml`, `requirements.txt` and the workbook seed files.

## 2. Create the Render service

In Render:

1. Choose **New → Blueprint**.
2. Connect GitHub.
3. Select the private `goodnature-r1m1-field-trial` repository.
4. Render reads `render.yaml` and proposes one paid web service with a 1 GB persistent disk.
5. Enter a strong value for the secret `R1M1_APP_PASSWORD`.
6. Apply the Blueprint.

The service uses:

- data folder: `/var/data`
- clean launch seed: `field_trial_data_clean_seed.xlsx`
- environment: `staging`
- HTTPS address supplied by Render

## 3. First deployment checks

When the deployment finishes:

1. Open the Render URL.
2. Confirm the password screen appears.
3. Sign in.
4. Confirm the banner says **STAGING**.
5. Confirm the data folder shown in the sidebar is `/var/data`.
6. Confirm the sites are Hutt River, Naenae and Tawa.
7. Confirm no historic visits, checks or follow-up tasks appear.
8. Confirm every trap has one clean open test window.
9. Complete the full desktop and phone release test.
10. Restart the Render service and confirm saved data and photos remain.

## 4. Move from staging to production

Only after the phone test and setup review:

1. In Render, change `R1M1_ENVIRONMENT` from `staging` to `production`.
2. Confirm camera assignments, route order, build versions and deployment start times.
3. Download a clean workbook backup.
4. Restrict the shared password to authorised trial users.
5. Begin real checks.

## Important operating limit

Use one active editor at a time. The app still uses one shared Excel workbook, so simultaneous saves can overwrite each other.


## Updating an existing Render deployment

After replacing the repository files with a newer release and committing the change, Render will redeploy automatically because `autoDeploy: true` is enabled in `render.yaml`.

Check the Render Events page and wait for the new deploy to show **Live** before testing the URL.
