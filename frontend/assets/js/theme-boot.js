// Runs before first paint (classic script in <head>) so a remembered or requested theme
// never flashes. ?theme=dark|light wins over the stored choice; no value follows the system.
(function () {
  var theme = null;
  try {
    var requested = new URLSearchParams(location.search).get("theme");
    if (requested === "dark" || requested === "light") theme = requested;
  } catch (e) { /* old browser: ignore the query */ }
  if (!theme) {
    try {
      var stored = localStorage.getItem("why-theme");
      if (stored === "dark" || stored === "light") theme = stored;
    } catch (e) { /* storage blocked: follow the system */ }
  }
  if (theme) document.documentElement.setAttribute("data-theme", theme);
})();
