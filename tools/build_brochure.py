"""Prints the one-page portfolios in marketing/ to PDF (Letter, one page each):

  owner-brochure.html    -> marketing/NTStays-owner-brochure.pdf     (owners: management, staging, renovation, cleaning)
  partner-brochure.html  -> marketing/NTStays-partner-brochure.pdf   (insurers, adjusters, housing providers)

Run:  python tools/build_brochure.py        (uses Microsoft Edge or Google Chrome in headless mode)
{{TOKENS}} and the route-map data come from site/data/stats.json, so re-run after re-running the stats. The PDFs
are attached to approved replies by the n8n workflow, so rebuild the workflow too (python n8n/build_workflow.py).
They include business figures (the owner one a revenue range): email them, don't link them from the site.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKETING = ROOT / "marketing"
BROCHURES = {"owner-brochure.html": "NTStays-owner-brochure.pdf", "partner-brochure.html": "NTStays-partner-brochure.pdf"}
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
]


def fill(html, st):
    tokens = {
        "{{RATING}}": f"{st['rating']['avg']:.2f}" if st.get("rating") else "",
        "{{REVIEWS}}": str(st.get("rating", {}).get("count", "")),
        "{{STAYS}}": str(st.get("stays_hosted", "")),
        "{{STATES}}": str(st.get("guest_us_states", "")),
        "{{COUNTRIES}}": str(st.get("guest_countries", "")),
    }
    for k, v in tokens.items():
        html = html.replace(k, v)
    return html.replace("/*__STATS__*/null", json.dumps(st))


def main():
    browser = next((b for b in BROWSERS if pathlib.Path(b).exists()), None)
    if not browser:
        sys.exit("No Edge or Chrome found; open the HTML in a browser and Print > Save as PDF (Letter, no margins).")
    st = json.loads((ROOT / "site" / "data" / "stats.json").read_text(encoding="utf-8"))
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    for src, pdf in BROCHURES.items():
        out = MARKETING / pdf
        filled = MARKETING / f"_{src}"  # next to the original, so the relative photo paths still work
        filled.write_text(fill((MARKETING / src).read_text(encoding="utf-8"), st), encoding="utf-8")
        out.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory() as profile:  # separate profile, so an open browser window can't take the job
                r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                                    f"--user-data-dir={profile}", "--virtual-time-budget=15000",  # fonts, photos, map
                                    f"--print-to-pdf={out}", filled.as_uri()], capture_output=True, text=True, timeout=180)
        finally:
            filled.unlink(missing_ok=True)
        if not out.exists():
            sys.exit(f"The browser didn't write {pdf}.\n{r.stderr[-1500:]}")
        pages = len(PdfReader(str(out)).pages) if PdfReader else "?"
        print(f"{out} ({out.stat().st_size // 1024} KB, {pages} page{'s' if pages != 1 else ''})")
        if pages not in (1, "?"):
            print(f"WARNING: {src} runs over one page; shorten its text")


if __name__ == "__main__":
    main()
