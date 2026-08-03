import permission from "./permission";
import debounce from "./debounce";

export default function (app) {
  if (!app.directive("permission")) {
    app.directive("permission", permission);
  }

  if (!app.directive("debounce")) {
    app.directive("debounce", debounce);
  }
}
