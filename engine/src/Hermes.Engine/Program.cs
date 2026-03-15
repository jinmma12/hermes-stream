using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.EntityFrameworkCore;
using Serilog;
using Hermes.Engine.Domain;
using Hermes.Engine.Grpc;
using Hermes.Engine.Infrastructure.Data;
using Hermes.Engine.Services;
using Hermes.Engine.Services.Monitors;
using Hermes.Engine.Services.Plugins;
using Hermes.Engine.Workers;

Log.Logger = new LoggerConfiguration()
    .WriteTo.Console()
    .CreateBootstrapLogger();

try
{
    var builder = WebApplication.CreateBuilder(args);

    // Serilog
    builder.Services.AddSerilog(config => config
        .ReadFrom.Configuration(builder.Configuration)
        .WriteTo.Console());

    // gRPC
    builder.Services.AddGrpc();

    // Kestrel: HTTP/2 for gRPC on port 50051
    var grpcPort = builder.Configuration.GetValue<int>("Grpc:Port", 50051);
    builder.WebHost.ConfigureKestrel(options =>
    {
        options.ListenAnyIP(grpcPort, o => o.Protocols = HttpProtocols.Http2);
    });

    // Database
    var connectionString = builder.Configuration.GetConnectionString("DefaultConnection");
    builder.Services.AddDbContext<HermesDbContext>(options =>
        options.UseNpgsql(connectionString));

    // HTTP client
    builder.Services.AddHttpClient();

    // Domain services
    builder.Services.AddSingleton<IConditionEvaluator, ConditionEvaluator>();
    builder.Services.AddScoped<ISnapshotResolver, SnapshotResolver>();
    builder.Services.AddScoped<IProcessingOrchestrator, ProcessingOrchestrator>();

    // Plugin system
    builder.Services.AddSingleton<IPluginRegistry, PluginRegistry>();
    builder.Services.AddSingleton<IPluginExecutor>(sp =>
        new PluginExecutor(
            sp.GetRequiredService<ILogger<PluginExecutor>>(),
            builder.Configuration.GetValue<int>("Engine:PluginTimeoutSeconds", 300)));
    builder.Services.AddScoped<IExecutionDispatcher, ExecutionDispatcher>();

    // Monitoring engine (singleton - manages all monitoring tasks)
    builder.Services.AddSingleton<IMonitoringEngine, MonitoringEngine>();

    // Background workers
    builder.Services.AddHostedService<MonitoringWorker>();
    builder.Services.AddHostedService<ProcessingWorker>();

    // Generic repositories
    builder.Services.AddScoped(typeof(IRepository<>), typeof(Repository<>));

    var app = builder.Build();

    // gRPC endpoint
    app.MapGrpcService<HermesEngineGrpcService>();

    // Auto-create database tables (EnsureCreated for dev; use migrations in prod)
    using (var scope = app.Services.CreateScope())
    {
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();
        await db.Database.EnsureCreatedAsync();
    }

    // Discover plugins
    var pluginRegistry = app.Services.GetRequiredService<IPluginRegistry>();
    var pluginsDir = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "plugins");
    if (Directory.Exists(pluginsDir))
        pluginRegistry.DiscoverPlugins(pluginsDir);

    Log.Information("Hermes Engine starting on gRPC port {Port}...", grpcPort);
    await app.RunAsync();
}
catch (Exception ex)
{
    Log.Fatal(ex, "Hermes Engine terminated unexpectedly");
}
finally
{
    await Log.CloseAndFlushAsync();
}
