# Public demo deployment

This repository includes a Render Blueprint for a small public CASEWORK demo. It runs the Python API and serves the front end from the same origin. It uses SQLite and creates the first Management Head from a password supplied privately in Render's setup form.

## Deploy

1. Open [Render's Blueprint deploy page](https://render.com/deploy) and connect `VenkatalakshmiRM/Crime-Record-Management`.
2. Render reads `render.yaml`. Before creating the service, enter a unique password of at least 12 characters for `CASEWORK_NEW_PASSWORD` in Render's private environment-variable prompt. Do not put that password in GitHub.
3. Create the service and wait for its deploy to finish.
4. Open the `onrender.com` URL shown in the Render dashboard, then sign in with username `casework_admin` and the password you entered.
5. Check `<your-service-url>/api/health` if the site reports a backend error.

The free web service is for demonstration only. It can sleep when idle, and its filesystem is temporary. SQLite records may be lost when Render restarts or redeploys the service; the first Management Head account is created again from the secret environment variable when the database starts empty. Use a persistent disk or a separately hosted database for records that must survive restarts; those options can incur charges.

The CASEWORK API and UI are deliberately served together. A GitHub Pages static site cannot run this Python API, so deploying only `index.html` there will not make login work.
