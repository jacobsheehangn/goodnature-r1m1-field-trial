# Security and operating notes

## Access

The deployment fails closed when `R1M1_APP_PASSWORD` is not configured. The password is compared without storing it in the repository. It must be set as a Render secret.

This is shared-password protection for a controlled pilot, not individual user authentication.

## Storage

`R1M1_DATA_DIR=/var/data` places the live workbook, evidence photos and automatic backups on the attached Render persistent disk.

The seed workbooks remain in the application image and are copied only when no live workbook exists.

## Backups

The app creates timestamped workbook backups before replacing the live workbook and retains the latest 20. Download external backups regularly because a persistent disk is not a full disaster-recovery system.

## Known constraint

One active editor at a time. Moving to a transactional database is required before broad or concurrent use.
