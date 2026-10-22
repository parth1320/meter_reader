# Solar meter collector + dashboard

GitHub Actions (cron, every 2 h) → `collector/collect.py` → Supabase (Postgres) → static dashboard on GitHub Pages.

The portal only refreshes the real-time read once per 6 h; running every 2 h is harmless
(rows are keyed by the meter's own timestamp, so repeats are ignored).

## Setup

1. **Supabase**: create a free project, open *SQL editor*, run `supabase/schema.sql`.
   Note *Project URL*, the `anon` key and the `service_role` key (Project settings → API).
2. **GitHub**: push this folder to a repo. *Settings → Secrets and variables → Actions*:
   `PORTAL_USER`, `PORTAL_PASS` (portal login), `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
   - If the headless login is rejected, use `PORTAL_COOKIE` instead (a `Cookie:` header copied
     from a logged-in browser). It only lasts as long as the portal session, so it needs refreshing.
3. Run *Actions → collect-meter-data → Run workflow* once and check the log.
4. Put the Project URL and **anon** key in `dashboard/config.js`, push, then
   *Settings → Pages → Source: GitHub Actions*. Dashboard goes live at `https://<user>.github.io/<repo>/`.

## Notes
- The anon key is public and read-only; anyone with the dashboard URL can read your meter data.
  Keep the repo/URL private-ish, or add Supabase Auth later.
- Never commit the `service_role` key or portal password.
- Free GitHub scheduled workflows are paused after 60 days without repo activity.
