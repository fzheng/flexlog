// Initialize PhotoSwipe on every session detail page.
// PhotoSwipeLightbox auto-discovers anchors matching the gallery selector.

(function () {
  "use strict";
  const gallery = document.getElementById("photo-gallery");
  if (!gallery || typeof PhotoSwipeLightbox === "undefined") return;

  const lightbox = new PhotoSwipeLightbox({
    gallery: "#photo-gallery",
    children: "a.photo-thumb",
    pswpModule: PhotoSwipe,
  });

  // The thumbnail <img> has already loaded the full file (we serve a
  // single resolution at one URL — thumbnails are CSS-cropped, not
  // server-resized). Read its naturalWidth/Height so the lightbox uses
  // each photo's TRUE aspect ratio instead of the placeholder
  // data-pswp-width/data-pswp-height set on the anchor (those are a
  // fallback for when the thumbnail hasn't loaded yet, e.g. a user
  // clicked before lazy-loading fired).
  lightbox.addFilter("itemData", (itemData) => {
    const a = itemData.element;
    if (a) {
      const img = a.querySelector("img");
      if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
        itemData.width = img.naturalWidth;
        itemData.height = img.naturalHeight;
      }
    }
    return itemData;
  });

  lightbox.init();
})();
