# Kurdistan cultural website

A responsive, mobile-first cultural magazine homepage built with plain HTML, CSS and JavaScript. It follows the provided reference layout and uses real photographs from Wikimedia Commons.

At 1000px and wider, the homepage switches to a wide hero, full-width category grid, and two-column featured/latest layout. At 1280px and wider, spacing and card proportions expand for larger monitors. The phone rules below 700px are retained unchanged.

## Run

Open `index.html` directly or serve the project directory with any static web server (for example, `python3 -m http.server 8000`).

## Images and licensing

The site loads resized Wikimedia Commons images using Wikimedia's file redirect endpoint. Credits and license/source links are included in the page under “Photograph credits & licenses”; story panels also credit their lead image. Image downloads were unavailable from the build environment, so images are not bundled locally. Internet access is required to display them. Please check each linked Commons file page for its current license and attribution details.

## Functionality

Search, the navigation menu, category links, story panels, English-only language notice, bottom navigation, and local story bookmarks work in the browser. Editorial cards are explicitly marked as sample previews rather than breaking news.
