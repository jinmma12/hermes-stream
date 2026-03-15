// Hermes Engine - .NET Worker Service
// Core engine for monitoring, processing, plugin execution, and NiFi integration.
// See engine/reference/ for Python reference implementations.

var builder = Host.CreateApplicationBuilder(args);

// TODO: Register engine services
// builder.Services.AddHostedService<MonitoringEngine>();
// builder.Services.AddHostedService<ProcessingOrchestrator>();
// builder.Services.AddSingleton<PluginRegistry>();
// builder.Services.AddSingleton<ExecutionDispatcher>();
// builder.Services.AddSingleton<ConditionEvaluator>();
// builder.Services.AddSingleton<SnapshotResolver>();

// TODO: Configure gRPC server for Python Web API communication
// builder.Services.AddGrpc();

// TODO: Configure database (EF Core + Npgsql)
// builder.Services.AddDbContext<HermesDbContext>(options =>
//     options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

// TODO: Configure Prometheus metrics
// builder.Services.AddSingleton<MetricServer>();

var host = builder.Build();
host.Run();
