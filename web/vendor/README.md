# Vendored third-party libraries

These files are checked in so the dashboard renders 3D without a network connection
(the app runs fully offline and ships as a frozen exe, so a CDN is not an option).

## three.js 0.185.1 - MIT License, (c) 2010-2025 three.js authors

Fetched from `https://unpkg.com/three@0.185.1/`:

| Local path | Upstream path |
| --- | --- |
| `three.module.min.js` | `build/three.module.min.js` |
| `three.core.min.js` | `build/three.core.min.js` |
| `addons/controls/OrbitControls.js` | `examples/jsm/controls/OrbitControls.js` |
| `addons/postprocessing/*.js` | `examples/jsm/postprocessing/*.js` |
| `addons/shaders/*.js` | `examples/jsm/shaders/*.js` |

`three.module.min.js` imports `./three.core.min.js` by relative path, so the two build
files must stay side by side. The addons import the bare specifier `three`, which the
import map in `web/index.html` points at `three.module.min.js`.

To upgrade: bump the version in every URL above, re-download the same file list, and
re-check that no addon has gained a relative import of a file that is not vendored
(`rg "from '\.\.?/" web/vendor/addons`).
