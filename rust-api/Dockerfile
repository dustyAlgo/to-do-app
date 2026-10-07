# builder and runtime share Debian bookworm, so the binary's glibc matches
FROM rust:1-slim-bookworm AS build
WORKDIR /src
COPY Cargo.toml ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN useradd --system --no-create-home app
COPY --from=build /src/target/release/rust-api /usr/local/bin/rust-api
USER app
EXPOSE 8080
CMD ["rust-api"]
