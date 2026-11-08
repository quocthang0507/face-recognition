// Runs before the page paints. Light is the default: it holds up best on a TV or
// projector in a lit classroom.
document.documentElement.dataset.theme = localStorage.getItem("smart-classroom-theme") || "light";
document.documentElement.dataset.display = localStorage.getItem("smart-classroom-display") || "desk";
