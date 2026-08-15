FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o app .

FROM alpine:3.21
WORKDIR /app
COPY --from=build /src/app .
EXPOSE 8080
CMD ["./app"]
