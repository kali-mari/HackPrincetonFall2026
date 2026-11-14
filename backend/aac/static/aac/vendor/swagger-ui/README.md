# Vendored Swagger UI

- Package: `swagger-ui-dist` version **5.31.0** (Apache-2.0).
- Source: https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.31.0.tgz
- Upstream: https://github.com/swagger-api/swagger-ui
- Tarball integrity: `sha512-zSUTIck02fSga6rc0RZP3b7J7wgHXwLea8ZjgLA3Vgnb8QeOl3Wou2/j5QkzSGeoz6HusP/coYuJl33aQxQZpg==`
- Included unchanged: `swagger-ui.css`, `swagger-ui-bundle.js`, `LICENSE`, `NOTICE`.

To reproduce, from the repository root:

```sh
python3 backend/aac/static/aac/vendor/swagger-ui/vendor.py
```

The script downloads the pinned public tarball, verifies SHA-512, and reads only the four named assets. Downloads are a development/setup operation; serving `/api/docs` needs no external service, npm, CDN, or online validator.

Review license/security updates before changing the pin. No source maps are included. In development Django staticfiles serves these assets. A non-debug deployment must collect and serve static files separately.
