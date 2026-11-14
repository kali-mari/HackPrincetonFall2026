"use strict";

window.addEventListener("load", () => {
  const element = document.getElementById("swagger-ui");
  window.ui = SwaggerUIBundle({
    url: element.dataset.schemaUrl,
    dom_id: "#swagger-ui",
    deepLinking: true,
    displayOperationId: true,
    showCommonExtensions: true,
    showExtensions: true,
    supportedSubmitMethods: ["get", "post", "patch", "delete"],
    validatorUrl: null,
    queryConfigEnabled: false,
    persistAuthorization: false,
  });
});
