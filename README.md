# ankush.space

Static portfolio for Ankush Wadehra. The design lives in Framer; `build_site.py`
mirrors the published site into `dist/` so it can be hosted anywhere.

## Layout

```
build_site.py   mirrors the published Framer site into a static bundle
dist/           generated output -- do not hand-edit, it is overwritten
```

## Build

```bash
python3 build_site.py https://ankush.space dist
```

The origin argument matters. Framer's runtime resolves its lazy-loaded chunks
with `new URL(chunk, base)`, and a relative base is not a valid URL base, so
asset URLs are rewritten absolute. **The origin must match where the bundle is
actually served** or the page renders as empty chrome.

To test locally, build against the loopback origin you will serve from:

```bash
python3 build_site.py http://127.0.0.1:8801 /tmp/verify
cd /tmp/verify && python3 -m http.server 8801
```

## Deploy

`dist/` is committed and treated as the build artifact. Hosts should serve it
directly with **no build command**. Running the build on the host would
re-scrape Framer on every deploy, making deploys depend on the project staying
published and on 134 asset fetches succeeding from a build container. The
bundle is a deterministic snapshot; ship the snapshot.

`dist/` contains directory indexes, so extensionless routes resolve without
rewrite rules.

- **Cloudflare Pages** (current host) — connect the repo, framework preset
  None, build command empty, output directory `dist`. Then add `ankush.space`
  under Custom domains; Cloudflare creates the apex DNS record itself.
  Redirect `www` to the apex, since the bundle is baked to the apex.
- **Netlify** — same, or drag `dist/` into the dashboard
- **GitHub Pages** — push `dist/` to `gh-pages`

The `*.pages.dev` preview URL renders as empty chrome. Expected: the ~200
absolute URLs point at `ankush.space`, so only the real domain serves assets.

## Updating content

The bundle is a snapshot. To change anything:

1. Edit the design in Framer
2. Publish there
3. Re-run the build: `python3 build_site.py https://ankush.space dist`
4. Commit the regenerated `dist/` and push — the host redeploys on push

## Known limitations

- **CMS is frozen.** Project pages are baked HTML. Content changes require a
  republish in Framer and a rebuild.
- **Contact form does not work.** It posts to Framer's backend, which will not
  accept requests from another origin. Needs Formspree, a Cloudflare Worker, or
  similar to function.
- One asset fetch reports as failed on every build: `fonts.gstatic.com/s/`, a
  truncated URL prefix picked up by the regex, not a real asset. Harmless.
- Three `framer.com/m/phosphor-icons/*` scripts still load from Framer's CDN.
  They render the caret, envelope, and GitHub icons and are imported from inside
  the mjs chunks, not the HTML. Not tracking. Vendoring them would mean editing
  minified chunks.

`build_site.py` strips Framer's `events.framer.com` beacon (removed outright)
and hides the "Made in Framer" badge (CSS, see `strip_framer`). The badge div is
left in the DOM on purpose: it sits inside React Suspense markers, and a
hydration mismatch here trips Framer's error boundary, which blanks the page.

## Source

Framer project: `QxpJ5zDhRO7ldVm4gP5O`
Published at: https://brilliant-imagine-119149.framer.app
