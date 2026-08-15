FROM rust:1.88 AS build
WORKDIR /app
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
WORKDIR /app
COPY --from=build /app/target/release/releaseguard-rust-demo .
EXPOSE 3000
CMD ["./releaseguard-rust-demo"]
