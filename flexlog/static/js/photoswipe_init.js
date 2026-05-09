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
  lightbox.init();
})();
