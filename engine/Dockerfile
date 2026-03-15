FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/Hermes.Engine/Hermes.Engine.csproj src/Hermes.Engine/
RUN dotnet restore src/Hermes.Engine/Hermes.Engine.csproj

COPY src/ src/
RUN dotnet publish src/Hermes.Engine/Hermes.Engine.csproj -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .

EXPOSE 50051
EXPOSE 9090

ENTRYPOINT ["dotnet", "Hermes.Engine.dll"]
