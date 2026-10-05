# URL service

## Caching
The URL service uses Redis to cache frequently accessed links.
The cache expiry is 300 seconds.

## Durable storage
PostgreSQL stores the durable URL records.
