# R1/M1 Verification Pipeline

This repository now enforces the permanent release definition of done.

## Hard rule

A release ZIP cannot be produced unless all mandatory local gates pass:

- Code and fixture-data gate
- Real browser workflow gate
- Required visual evidence gate

The package script reads `evidence/gate-results.json` and exits with an error if any mandatory gate is not `PASS`.

## Evidence produced

Every run uploads one evidence bundle containing:

- code/data gate JSON
- browser JUnit results
- screenshots at 390 px, 430 px and desktop
- Playwright traces and videos when a browser test fails
- a single gate report

## Release sequence

1. Push the repository to `main`, or run **R1M1 release evidence** manually.
2. GitHub Actions starts the app locally with disposable workbook data.
3. Browser tests complete the real affected workflows.
4. Resulting workbook data is checked.
5. Required screenshots are captured.
6. The workflow fails when any mandatory result or screenshot is missing.
7. A candidate ZIP is created only after the mandatory gates pass.
8. The read-only Render smoke gate then checks the deployed environment.

## Current application status

The included v8.7.5 application remains withdrawn. This package proves the verification system first; it does not declare the application field-ready.
