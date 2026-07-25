# Free Roku remote for everyone

**Product link:** https://kurbaitaev.github.io/hisense-remote/

This is a **free alternative to paid App Store Roku remotes**.  
Anyone opens the page on their phone, connects to **their** TV on **their** Wi‑Fi, and controls it. No account. No fee.

```
Phone ── home Wi‑Fi ──► Roku TV :8060
  ▲
  └── static web page (GitHub Pages / Cloudflare / etc.)
```

---

## Tell people

> Free Roku remote (no App Store):  
> **https://kurbaitaev.github.io/hisense-remote/**  
>  
> Same Wi‑Fi as your TV. On the TV: Settings → System → Advanced →  
> Control by mobile apps → **Enabled**.  
> Then open the link and use it. Add to Home Screen if you want.

---

## Host your own copy

Only the **`web/`** folder is required.

### GitHub Pages (this repo)

Already live. After editing `web/`:

```bash
git subtree split --prefix web -b gh-pages
git push origin gh-pages --force
```

### Cloudflare Pages

```bash
npx wrangler pages deploy web --project-name=roku-remote
```

Build output directory: `web`.

---

## Optional: voice / advanced (developers)

The Python server under `server/` is for people who want mic + smarter play **on their own home network**.  
Regular users never need it — the free remote is `web/` only.
