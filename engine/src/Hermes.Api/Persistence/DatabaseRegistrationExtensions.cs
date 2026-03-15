using Hermes.Api.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Hermes.Api.Persistence;

public static class DatabaseRegistrationExtensions
{
    public static IServiceCollection AddHermesApiPersistence(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddDbContext<HermesApiDbContext>((serviceProvider, options) =>
        {
            var settings = serviceProvider.GetRequiredService<IOptions<DatabaseOptions>>().Value;
            var mode = string.IsNullOrWhiteSpace(settings.Mode) ? "inmemory" : settings.Mode.Trim().ToLowerInvariant();
            var provider = string.IsNullOrWhiteSpace(settings.Provider) ? "postgres" : settings.Provider.Trim().ToLowerInvariant();

            if (mode == "database")
            {
                var connectionString = provider == "sqlserver"
                    ? settings.ConnectionStrings.SqlServer
                    : settings.ConnectionStrings.Postgres;

                if (provider == "sqlserver")
                {
                    options.UseSqlServer(connectionString);
                }
                else
                {
                    options.UseNpgsql(connectionString);
                }

                return;
            }

            options.UseInMemoryDatabase("HermesPrototype");
        });

        services.AddHostedService<SchemaRevisionSeeder>();

        return services;
    }
}
