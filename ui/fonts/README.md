# ui/fonts

Two typefaces, declared in `ui/tokens.css`, which every page links first.

    PlusJakartaSans-VariableFont_wght.woff2     body, controls, labels
    EBGaramond-VariableFont_wght.woff2          headings, the app name, agent names

Drop both files in this folder and they take effect on the next reload. No
build step, no install, nothing to register with Windows.

Both are variable fonts, so one file covers the whole weight range and there
are no separate Regular, SemiBold and Bold downloads to keep in step. If you
end up with the static versions instead, name them `PlusJakartaSans-Regular`
and `EBGaramond-Regular` and `tokens.css` will pick those up as the second
source in each `@font-face`.

Both are under the SIL Open Font License. Google Fonts serves the variable
woff2 for each. The upstream projects are github.com/tokotype/PlusJakartaSans
and github.com/octaviopardo/EBGaramond12.

## Why they are not loaded from a CDN

There is deliberately no font CDN link on any page here. This app serves plain
http on loopback and runs on machines with no internet at all, and a blocking
stylesheet request to a host that will never answer is a blank page for however
long the browser takes to give up.

## Nothing breaks if the files are absent

`--sans` falls through to Segoe UI and `--serif` falls through to a system
Garamond and then to Georgia. No layout depends on the exact metrics of any of
them. The page will look plainer and it will still be correct.

## One thing to know if you move these files

The `@font-face` paths in `tokens.css` are relative to that stylesheet, so they
read `fonts/...`. `prototype_agents.py` inlines the whole of `tokens.css` into
a page that sits one level up at the repo root, and rewrites those paths to
`ui/fonts/...` on the way through. Any other generator that inlines this
stylesheet from a different directory has to do the same thing. A missed
rewrite is silent: you get the fallback stack and no error anywhere.
