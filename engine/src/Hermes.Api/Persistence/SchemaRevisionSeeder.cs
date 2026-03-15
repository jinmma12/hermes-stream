using Hermes.Api.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Hermes.Api.Persistence;

public sealed class SchemaRevisionSeeder : IHostedService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly DatabaseOptions _options;

    public SchemaRevisionSeeder(IServiceProvider serviceProvider, IOptions<DatabaseOptions> options)
    {
        _serviceProvider = serviceProvider;
        _options = options.Value;
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        await using var scope = _serviceProvider.CreateAsyncScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<HermesApiDbContext>();

        await dbContext.Database.EnsureCreatedAsync(cancellationToken);

        var provider = string.IsNullOrWhiteSpace(_options.Provider) ? "postgres" : _options.Provider.Trim().ToLowerInvariant();
        var schema = string.IsNullOrWhiteSpace(_options.Schema) ? "hermes" : _options.Schema.Trim();
        const string revisionKey = "2026-03-15-prototype-bootstrap-v1";

        var exists = await dbContext.SchemaRevisions.AnyAsync(
            x => x.Provider == provider &&
                 x.SchemaName == schema &&
                 x.RevisionKey == revisionKey,
            cancellationToken);

        if (exists)
        {
            return;
        }

        dbContext.SchemaRevisions.Add(new SchemaRevision
        {
            Id = Guid.NewGuid(),
            Provider = provider,
            SchemaName = schema,
            RevisionKey = revisionKey,
            AppliedBy = "hermes-api",
            Notes = "Prototype bootstrap baseline for schema-aware Hermes installs",
            AppliedAt = DateTimeOffset.UtcNow
        });

        await dbContext.SaveChangesAsync(cancellationToken);
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
