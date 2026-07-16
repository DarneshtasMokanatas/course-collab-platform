const menuButton = document.querySelector(".menu-toggle");
const primaryNavigation = document.querySelector("#primary-navigation");

if (menuButton && primaryNavigation) {
  menuButton.hidden = false;
  const mobileNavigation = window.matchMedia("(max-width: 56rem)");
  const syncNavigation = (isMobile) => {
    primaryNavigation.hidden = isMobile;
    menuButton.setAttribute("aria-expanded", "false");
  };
  syncNavigation(mobileNavigation.matches);

  menuButton.addEventListener("click", () => {
    const expanded = menuButton.getAttribute("aria-expanded") === "true";
    menuButton.setAttribute("aria-expanded", String(!expanded));
    primaryNavigation.hidden = expanded;
  });

  mobileNavigation.addEventListener("change", (event) => syncNavigation(event.matches));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !primaryNavigation.hidden && mobileNavigation.matches) {
      primaryNavigation.hidden = true;
      menuButton.setAttribute("aria-expanded", "false");
      menuButton.focus();
    }
  });
}

const dialog = document.querySelector("#confirmation-dialog");
const dialogMessage = document.querySelector("#confirmation-message");
const dialogAccept = document.querySelector("#confirmation-accept");
const dialogCancel = document.querySelector("#confirmation-cancel");
let pendingForm = null;

if (dialog && dialogMessage && dialogAccept && dialogCancel) {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "true") {
        return;
      }
      event.preventDefault();
      pendingForm = form;
      dialogMessage.textContent = form.dataset.confirm;
      dialogAccept.classList.toggle("button-danger", form.dataset.confirmTone === "danger");
      dialog.showModal();
      dialogCancel.focus();
    });
  });

  dialogAccept.addEventListener("click", () => {
    if (!pendingForm) {
      return;
    }
    pendingForm.dataset.confirmed = "true";
    dialog.close();
    pendingForm.requestSubmit();
  });

  dialogCancel.addEventListener("click", () => {
    dialog.close();
  });

  dialog.addEventListener("close", () => {
    pendingForm?.querySelector("button, input, select, textarea, a")?.focus();
    pendingForm = null;
  });
}

document.querySelectorAll("form[data-loading]").forEach((form) => {
  form.addEventListener("submit", () => {
    const submitter = form.querySelector('button[type="submit"]');
    if (!submitter) {
      return;
    }
    window.requestAnimationFrame(() => {
      submitter.dataset.originalText = submitter.textContent;
      submitter.disabled = true;
      submitter.classList.add("is-loading");
      submitter.setAttribute("aria-busy", "true");
      if (submitter.dataset.loadingText) {
        submitter.textContent = submitter.dataset.loadingText;
      }
    });
  });
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  document.querySelectorAll(".user-menu[open]").forEach((menu) => {
    menu.removeAttribute("open");
    menu.querySelector("summary")?.focus();
  });
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll(".is-loading").forEach((button) => {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    if (button.dataset.originalText) {
      button.textContent = button.dataset.originalText;
      delete button.dataset.originalText;
    }
  });
});
