# CDP Recording PoC

This directory is for quick validation of the new external Chrome + CDP recording route.

The first script records `https://www.kehuanxiongmao.com` while scrolling the page:

```powershell
node .\cdp-poc\record_kehuanxiongmao.js
```

To create or refresh the login state, launch a visible Chrome window with the same CDP profile:

```powershell
node .\cdp-poc\login_profile.js
```

Log in manually, then return to the terminal and press Enter. The script exports cookies,
localStorage, and sessionStorage to `profiles/<profile-id>/auth_state.json`, then closes Chrome.
Later recording runs restore that auth state before capture.

Outputs are written under:

```text
cdp-poc/output/<task-id>/
```
