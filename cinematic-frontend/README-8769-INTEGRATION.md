# NYAYA: Update the website already running on port 8769

This update contains ONLY two replacement frontend files:

- dashboard/dashboard.html — Chezhil premium dashboard UI
- dashboard/command-center-v2.css — additional presentation-only dashboard styling

## Apply to your existing port-8769 project (recommended)
1. Keep your existing CMD server window open (the one serving port 8769).
2. Open Downloads/NYAYA-CINEMATIC-SCROLL-RESTORED (2)/dashboard on your laptop, or whichever extracted folder the 8769 server is serving.
3. Back up its existing dashboard.html if you want an easy rollback.
4. Copy BOTH files from this ZIP's dashboard folder into that existing dashboard folder. Choose Replace when Windows asks about dashboard.html.
5. In Chrome open http://127.0.0.1:8769/index.html and press Ctrl+F5. Open Explore Dashboard. The premium dashboard should appear within the SAME website.

Do not copy to the old port 8770 project. Do not modify app.js, API paths, or backend files.

## Alternative: Entire merged project
NYAYA-8769-CINEMATIC-PLUS-CHEZHIL.zip contains the two changes already installed. If using its START-NYAYA.cmd, first stop the *old* 8769 server (Ctrl+C), then start the new extracted project, since only one process can use port 8769 at a time.

This is frontend-only. Live backend operation cannot be confirmed from an offline preview.
