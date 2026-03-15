using Hermes.Api.Endpoints;
using Hermes.Api.Services;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSingleton<IHermesReadStore, InMemoryHermesReadStore>();
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
});

var app = builder.Build();

app.MapHermesSystemEndpoints();
app.MapHermesReadEndpoints();

app.Run();

public partial class Program
{
}
