import { ApiError, api } from "./common.js";

const form = document.getElementById("login-form");
const error = document.getElementById("login-error");

function nextPage() {
  const next = new URLSearchParams(location.search).get("next") || "/";
  // Only same-site paths, never "//other.site" or absolute URLs.
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = form.username.value.trim();
  const password = form.password.value;
  if (!username || !password) {
    error.textContent = "Enter your username and password.";
    error.hidden = false;
    return;
  }
  const button = form.querySelector("button");
  button.disabled = true;
  error.hidden = true;
  try {
    await api("/api/login", { method: "POST", body: { username, password } });
    location.replace(nextPage());
  } catch (err) {
    error.textContent = err instanceof ApiError ? err.message : "Could not reach the server. Check your connection.";
    error.hidden = false;
    form.password.value = "";
    form.password.focus();
  } finally {
    button.disabled = false;
  }
});
