# Strømligning API

API documentation: https://stromligning.dk/api/docs/

The integration uses `https://stromligning.dk/api` through `pystromligning`:

- `GET /suppliers/find?lat=...&long=...` resolves the grid supplier at Home Assistant's home location.
- `GET /companies?region=...` lists products. Each product's `productType` identifies `fixed` or `variable` pricing.
- `GET /prices` retrieves the price breakdown for the selected product, supplier, date, aggregation and forecast setting.

Fixed-price products require the `electricityPrice` query parameter in kr/kWh
excluding VAT. The integration stores the user's agreed electricity price
including VAT and divides by 1.25 before passing it to the library. A live request
with `electricityPrice=1.00` returned an electricity component with `value=1`,
`vat=0.25` and `total=1.25`. Grid tariffs and taxes remain separate components.

The `fixedPrice` returned by the product catalogue is not used as the customer's
agreement price. Product type is retained by the library; detection does not
rely on names or deliberately failed price requests. Missing agreement prices
are reported locally before requesting `/prices`.

Library requests have a 60-second timeout. The library also supports
`https://staging.stromligning.dk/api` for development; this integration uses the
production API.

The manifest and test requirements use `pystromligning==0.2.0` from PyPI.
