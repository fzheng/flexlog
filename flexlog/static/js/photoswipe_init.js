// Initialize PhotoSwipe on every session detail page.
// PhotoSwipeLightbox auto-discovers anchors matching the gallery selector.
// We run it twice: once for the photos grid, once for the link-thumbnail
// gallery (each has its own carousel — clicking a link thumb opens only
// other link thumbs, not the regular photos).

(function () {
  "use strict";
  if (typeof PhotoSwipeLightbox === "undefined") return;

  function initGallery(gallerySelector, childSelector) {
    const gallery = document.querySelector(gallerySelector);
    if (!gallery) return;
    if (!gallery.querySelector(childSelector)) return;  // nothing to open

    const lightbox = new PhotoSwipeLightbox({
      gallery: gallerySelector,
      children: childSelector,
      pswpModule: PhotoSwipe,
    });

    // The thumbnail <img> has already loaded the full file (we serve a
    // single resolution at one URL — thumbnails are CSS-cropped, not
    // server-resized). Read its naturalWidth/Height in the domItemData
    // filter so the lightbox uses each image's TRUE aspect ratio instead
    // of the placeholder data-pswp-width/data-pswp-height on the anchor.
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
  }

  initGallery("#photo-gallery", "a.photo-thumb");
  initGallery("#link-thumb-gallery", "a.link-thumb-anchor");
})();
