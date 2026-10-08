# ui/fonts

The launch screen sets its titles and main text blocks in EB Garamond. Drop
these two files here and they take effect on the next reload:

    EBGaramond-Regular.woff2
    EBGaramond-SemiBold.woff2

EB Garamond is under the SIL Open Font License. Get the two weights as woff2
from the Google Fonts entry for EB Garamond, or from the upstream project at
github.com/octaviopardo/EBGaramond12.

There is deliberately no link to a font CDN in `launch.html`. This app serves
plain http on loopback and runs on machines with no internet at all, and a
blocking stylesheet request to a host that will never answer is a blank page
for however long the browser takes to give up.

Nothing breaks if the files are absent. The `--serif` stack in `tokens.css`
falls through to a system Garamond and then to Georgia, and no layout on the
page depends on the exact metrics of any of them.
