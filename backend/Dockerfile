# syntax=docker/dockerfile:1
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY scripts/mvn-retry.sh /usr/local/bin/mvn-retry
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2,sharing=locked sh /usr/local/bin/mvn-retry dependency:go-offline
COPY src src
RUN --mount=type=cache,target=/root/.m2,sharing=locked sh /usr/local/bin/mvn-retry -DskipTests package
FROM eclipse-temurin:17-jre AS runtime-base
WORKDIR /app
USER 10001
EXPOSE 8080
ENTRYPOINT ["java","-jar","app.jar"]

# CI has already compiled and tested this exact JAR with mvn verify.
FROM runtime-base AS verified
COPY target/media-backend-0.1.0-SNAPSHOT.jar app.jar

# Default local/deployment build still compiles from source.
FROM runtime-base AS runtime
COPY --from=build /app/target/media-backend-0.1.0-SNAPSHOT.jar app.jar
