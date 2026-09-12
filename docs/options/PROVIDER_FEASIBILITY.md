# Options provider feasibility

## yfinance

The current adapter can request expiries and a chain for symbols accepted by
yfinance. The API response additionally downgrades each capability to
`UNAVAILABLE` when the returned snapshot contains no non-null values for that
field. Adapter support is therefore not treated as proof that a particular
symbol response contains OI, volume, IV, quotes, or Greeks.

## INDmoney / INDstocks

Options capability is **INDMONEY_SESSION_ONLY / UNVERIFIED**. The repository
has authenticated historical-market-data support through its existing
market-data boundary, but no safe, documented server-callable INDmoney
options-chain contract was verified. Credentials, OTPs, browser sessions, and
tokens must not be automated or copied into options persistence.

This classification is intentionally non-blocking and does not claim options
support. A future change may promote it only with a bounded provider probe and
documented response contract.
