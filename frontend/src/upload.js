export function uploadFile(url, file, onProgress, headers = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.timeout = 120000;
    xhr.ontimeout = () =>
      reject(new Error("Upload timed out. Check its status before retrying."));
    xhr.setRequestHeader("Content-Type", file.type);
    xhr.setRequestHeader("If-None-Match", "*");
    for (const [name, value] of Object.entries(headers || {})) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error("Storage rejected the upload."));
    xhr.onerror = () =>
      reject(new Error("Upload interrupted. Check your connection."));
    xhr.send(file);
  });
}
export function metadata(form) {
  return Object.fromEntries(
    [
      "title",
      "description",
      "species",
      "location",
      "capturedAt",
      "contributor",
      "usageNote",
    ].map((key) => [key, form.get(key) || null]),
  );
}
