// Wires Cropper.js to the avatar file input on person new/edit forms.
//
// HTML contract (rendered by Jinja):
//   <input type="file" id="avatar-file" accept="image/jpeg,image/png,image/webp">
//   <div id="avatar-cropper-area" hidden><img id="avatar-cropper-img"></div>
//   <button type="button" id="avatar-crop-save" hidden>Crop & save</button>
//   <button type="button" id="avatar-crop-reset" hidden>Reset crop</button>
//   <input type="hidden" name="avatar_blob" id="avatar-blob">
//   <p id="avatar-cropped-preview-wrap" hidden>
//     <img id="avatar-cropped-preview" alt="Avatar preview" width="96" height="96">
//   </p>
//
// On file pick: load image into cropper.
// On Crop & save: set hidden input to canvas dataURL (image/jpeg, q=0.92), show preview.
// On Reset crop: re-pick file required.

(function () {
  "use strict";
  if (typeof Cropper === "undefined") return;

  document.addEventListener("DOMContentLoaded", function () {
    const fileInput = document.getElementById("avatar-file");
    if (!fileInput) return;
    const img = document.getElementById("avatar-cropper-img");
    const area = document.getElementById("avatar-cropper-area");
    const saveBtn = document.getElementById("avatar-crop-save");
    const resetBtn = document.getElementById("avatar-crop-reset");
    const blobInput = document.getElementById("avatar-blob");
    const previewWrap = document.getElementById("avatar-cropped-preview-wrap");
    const preview = document.getElementById("avatar-cropped-preview");
    let cropper = null;

    fileInput.addEventListener("change", function () {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const url = URL.createObjectURL(file);
      img.src = url;
      area.hidden = false;
      saveBtn.hidden = false;
      resetBtn.hidden = false;
      if (cropper) cropper.destroy();
      cropper = new Cropper(img, {
        aspectRatio: 1,
        viewMode: 1,
        autoCropArea: 1,
        background: false,
        movable: true,
        zoomable: true,
        rotatable: false,
        scalable: false,
        cropBoxResizable: true,
      });
    });

    saveBtn.addEventListener("click", function () {
      if (!cropper) return;
      const canvas = cropper.getCroppedCanvas({
        width: 512,
        height: 512,
        imageSmoothingQuality: "high",
      });
      const dataURL = canvas.toDataURL("image/jpeg", 0.92);
      blobInput.value = dataURL;
      preview.src = dataURL;
      previewWrap.hidden = false;
    });

    resetBtn.addEventListener("click", function () {
      if (cropper) cropper.reset();
      blobInput.value = "";
      previewWrap.hidden = true;
    });
  });
})();
