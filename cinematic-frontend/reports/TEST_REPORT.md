# NYAYA clarity upgrade — executed verification

## Result
26/26 real Chromium interaction/layout/resource checks passed in the final run at desktop 1920×1080 and mobile 390×844. 78 mocked contract/static checks passed, plus JavaScript syntax checks for all three scripts. These categories are distinct.

All five scene images decoded. Scrolling through all five sections, scene navigation, sound ON/OFF, motion pause/resume, map-layer toggle, REVIEW explanation, dashboard opening/closing, recorded dashboard initialization and four dashboard tabs were exercised. Mobile tests checked horizontal overflow in each scene. Desktop scene captures and the mobile landing capture were visually inspected.

No uncaught JavaScript errors and no failed network requests were recorded. One expected HTTP 404 occurred at /api/v1/system because the standalone HTTP server has no backend; the dashboard initialized using its existing recorded fixtures. No image/script requests returned missing resources in this final run.

The earlier screenshot-heavy rerun timed out capturing a page. The final functional run omitted screenshots and completed all checks. Captures from the completed first run were inspected; this timeout is not represented as a successful capture.

## Measured scene assets
| Scene | Actual native dimensions | Method |
|---|---|---|
| storm-city | 1460 × 1078 | AI reconstruction |
| disaster-intelligence | 1774 × 887 | AI reconstruction |
| human-story | 682 × 324 | Preserved crop + modest sharpening |
| command-center | 1639 × 959 | AI reconstruction |
| earth-sunrise | 1686 × 933 | AI reconstruction |

The original single reference is 682×2048, with each scene only 682 pixels wide. No delivered scene is claimed to be genuine 4K. The minimum Full HD source target is NOT met across all five scenes. Four assets contain reconstructed detail; the human-story request was rejected by the image service and its original 682×324 crop is retained with modest sharpening. Fine scenery can differ from the reference. The human scene still has baked-in visual elements; opaque live cards conceal their underlying text where possible.

## Source preservation
app.js, cinematic.js, audio-engine.js, styles.css and all 16 fixture files remain byte-identical to the uploaded project (20/20 checks). The HTML scene structure and all foreground motion elements remain. Changes are background URLs, narrowly scoped CSS, and local copies of the exact pinned dashboard dependencies. No backend, Git repository, branch or deployment was touched.

The existing animation system is native CSS/JavaScript, not GSAP. Animation code was not replaced. Live banking API correctness, real-device GPU performance and subjective audio quality are not verified by these tests. Web Audio activation and mute state were verified in Chromium.

## Reproduction
Run `python dashboard/tests/run-checks.py` for the 78 checks and syntax validation. See tests/browser-results.json, tests/upgrade-checks.txt and tests/upgrade-source-preservation.json for raw results. Browser automation source is tests/browser-checks.cjs; it requires Playwright and installed Chromium, and a local server at NYAYA_TEST_URL (default http://127.0.0.1:8765/dashboard/). Run from the package root.
