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
  // server-resized). Read its naturalWidth/Height in the domItemData
  // filter so the lightbox uses each photo's TRUE aspect ratio instead
  // of the placeholder data-pswp-width/data-pswp-height on the anchor.
  // `domItemData` runs at slide-collection time with the link element
  // passed in explicitly — that's where the width/height get baked in
  // for both the open transition AND the in-lightbox image sizing.
  lightbox.addFilter("domItemData", (itemData, element, linkEl) => {
    const anchor = linkEl || element;
    if (anchor) {
      const img = anchor.querySelector("img");
      if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
        itemData.width = img.naturalWidth;
        itemData.height = img.naturalHeight;
        itemData.w = img.naturalWidth;   // some PhotoSwipe v5 builds key on .w/.h
        itemData.h = img.naturalHeight;
      }
    }
    return itemData;
  });

  lightbox.init();
})();
