# Solar meter collector + dashboard

Your PC (`collector/local.py`) → Supabase (Postgres) → static dashboard on GitHub Pages.

The portal login is protected by reCAPTCHA, which rejects automated logins from GitHub's servers.
So you log in by hand in a browser window, and the script keeps that session alive and
collects data every 2 h. The portal only refreshes the real-time read once per 6 h;
rows are keyed by the meter's own timestamp, so repeats are ignored.

## One-time setup

1. **Supabase**: create a free project, run `supabase/schema.sql` in the SQL editor.
2. **`.env`** in the project root (never commit it):
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_SERVICE_KEY=your-service-role-key
   ```
3. **Python packages** (once):
   ```
   pip install playwright
   playwright install chromium
   ```
4. **Test**: `python collector/local.py --once` - a browser opens, log in, wait; it prints
   `upserted … row(s)`. Check the tables in Supabase.
5. **Run all the time**: `python collector/local.py`, or make it start with Windows:
   `schtasks /Create /SC ONLOGON /TN MeterCollector /TR "cmd /c cd /d <project folder> && python collector\local.py"`
   When the session expires, the login window opens again; log in and it carries on.

## Dashboard
Put the Project URL and **anon** key in `dashboard/config.js`, push, then
*Settings → Pages → Source: GitHub Actions*. It goes live at `https://<user>.github.io/<repo>/`.

## Notes
- The anon key is public and read-only; anyone with the dashboard URL can read your meter data.
- Never commit the `service_role` key, `.env` or `.session`.
- The GitHub workflow `collect-meter-data` is manual-only and will fail on login; it is kept
  only for the `PORTAL_COOKIE` option.
