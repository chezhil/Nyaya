# NYAYA — CINEMATIC + DASHBOARD FINAL

Extract this ZIP and open a terminal in the extracted folder:

```sh
python -m http.server 5500 --directory dashboard
```

Windows alternative: `py -m http.server 5500 --directory dashboard`

Story: http://localhost:5500/
Dashboard: http://localhost:5500/dashboard.html

Explore Dashboard opens the upgraded dashboard. Return to Story returns to the cinematic page. The modal's existing close button also returns to the story. Use Ctrl+F5 after replacing an older preview.

All approved cinematic backgrounds and landing-page files remain unchanged. API/business logic is preserved. Offline preview uses the existing recorded fixtures. See dashboard/DASHBOARD_UPGRADE_REPORT.md for 18 new browser checks and the source-attachment limitation.
