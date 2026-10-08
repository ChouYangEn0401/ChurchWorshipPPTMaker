// 第一次畫面出來之前就決定深色／淺色，才不會閃一下。預設跟著作業系統。
(function () {
  try {
    var saved = localStorage.getItem("wppt.theme");
    var dark = saved ? saved === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  } catch (_) {
    document.documentElement.dataset.theme = "light";
  }
})();
