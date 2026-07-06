# Google & Apple sign-in — setup guide

The backend + frontend code for both providers is fully wired. To turn either
one on, you only need to obtain provider credentials and paste them into
`backend/.env`. No code changes required.

Until you configure credentials, the buttons on the sign-in screen will still
appear but will return a **503 "OAuth is not configured"** error when clicked —
so users can just use email/password until you finish setup.

---

## Google

**Time:** ~5 minutes.
**Cost:** free.

1. Go to https://console.cloud.google.com/apis/credentials
2. If you don't have a project yet, create one (top bar → **New Project**).
3. Set up the **OAuth consent screen** (menu on the left):
   - User type: **External**
   - App name: your app's name (e.g. "Cutwise" or whatever you're calling it)
   - User support email + developer email: your address
   - Scopes: no changes needed (openid, email, profile are added automatically)
   - Test users: add your own email address so you can sign in while the app
     is unverified
   - Save
4. Back on the **Credentials** page → **Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Name: any label (e.g. "Cutwise dev")
   - **Authorized JavaScript origins** (dev): `http://localhost:5173`
   - **Authorized redirect URIs** (dev):
     `http://localhost:8000/api/auth/oauth/google/callback`
   - Create → copy the **Client ID** and **Client Secret**
5. In `backend/.env`:
   ```
   GOOGLE_CLIENT_ID=<paste>
   GOOGLE_CLIENT_SECRET=<paste>
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/oauth/google/callback
   ```
6. Restart `dev_up.py`. **Continue with Google** now works.

For production: add your production origin + redirect URI to the same client,
or create a separate client with production URIs, and update `.env` on the
server.

---

## Apple

**Time:** ~30 minutes. Requires an Apple Developer membership (**$99/year**).
More complex than Google because Apple uses a different flow (form POST +
short-lived JWTs signed with a `.p8` private key).

If you don't have a paid Apple Developer account, skip Apple and use only
Google + email/password.

1. Sign in to https://developer.apple.com/account/
2. **Certificates, Identifiers & Profiles → Identifiers → +**:
   - Type: **Services IDs** (NOT App IDs)
   - Description: your app's name
   - Identifier: reverse-DNS style, e.g. `com.example.cutwise.web` — this becomes
     your `APPLE_CLIENT_ID`
   - Continue → Register
3. Click the Services ID you just made → **Configure Sign in with Apple**:
   - Primary App ID: pick an App ID if you have one, or create one
   - Domains and Subdomains: `localhost` for dev (this may error — see the
     "localhost workaround" below)
   - Return URLs: `http://localhost:8000/api/auth/oauth/apple/callback`
   - Save
4. **Keys → +**:
   - Key name: e.g. "Cutwise Sign in with Apple"
   - Check **Sign in with Apple**, click **Configure** → pick the Primary App
     ID → Save
   - Continue → Register → **Download** the `.p8` file (you only get one shot)
   - Copy the **Key ID** shown after download — this is `APPLE_KEY_ID`
5. Find your **Team ID**: top-right of the developer portal, or on the
   membership page. Ten-character alphanumeric.
6. Store the `.p8` file somewhere the backend can read it, e.g.
   `backend/secrets/AuthKey_XXXXXXX.p8` (add `secrets/` to `.gitignore`).
7. In `backend/.env`:
   ```
   APPLE_CLIENT_ID=com.example.cutwise.web
   APPLE_TEAM_ID=<10-char team id>
   APPLE_KEY_ID=<10-char key id>
   APPLE_PRIVATE_KEY_PATH=./secrets/AuthKey_XXXXXXX.p8
   APPLE_REDIRECT_URI=http://localhost:8000/api/auth/oauth/apple/callback
   ```
8. Restart `dev_up.py`. **Continue with Apple** now works.

### localhost workaround

Apple's console **doesn't accept `localhost`** as a domain. Two options:

- **Recommended for dev:** use a service like `ngrok` or `cloudflared` to
  tunnel `https://<random>.ngrok-free.app` → `http://localhost:8000`, and use
  that as your Return URL + Domain. Update `APPLE_REDIRECT_URI` accordingly.
- **Or:** register a real dev domain (e.g. `dev.example.com` pointing to
  `127.0.0.1` via `hosts` file) and use that.

Once you're on a real production domain, this workaround goes away.

---

## What each provider gives us

Both providers, on successful sign-in:

- Create a `User` row on first sign-in (or link to an existing one by email
  when Google returns `email_verified=true`)
- Set `email_verified_at` on the user (this is what the export-flow gate
  reads — OAuth users skip the email-verification step because the provider
  already verified them)
- Create an `Identity` row so the user can sign in again with the same
  provider

## When it doesn't work

Common errors + causes:

| Error / behavior | Likely cause |
|---|---|
| Sign-in button → 503 "OAuth is not configured" | Missing or blank `<PROVIDER>_CLIENT_ID` / `_CLIENT_SECRET` |
| Redirect to `?auth=error&provider=google&reason=access_denied` | User cancelled the Google flow |
| Redirect to `?auth=error&provider=apple&reason=invalid_client` | `APPLE_CLIENT_ID` mismatch, `.p8` not readable, or Team ID wrong |
| Google `redirect_uri_mismatch` shown by Google | The URI in `.env` doesn't exactly match one added in the Google Console |
| Apple `unauthorized_client` | The Services ID isn't configured for Sign in with Apple, or the key is bound to the wrong App ID |

## Testing without real credentials

The auth test suite mocks both providers, so you can iterate on the OAuth
flow (state validation, error redirects, callback shape) with:
```bash
pytest backend/tests/test_auth_integration.py
```
Nothing on that suite hits a real Google or Apple endpoint.
