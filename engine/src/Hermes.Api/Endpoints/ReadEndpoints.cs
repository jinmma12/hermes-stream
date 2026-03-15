using Hermes.Api.Services;

namespace Hermes.Api.Endpoints;

public static class ReadEndpoints
{
    private static readonly HashSet<string> DefinitionKinds = new(StringComparer.OrdinalIgnoreCase)
    {
        "collectors",
        "algorithms",
        "transfers"
    };

    public static WebApplication MapHermesReadEndpoints(this WebApplication app)
    {
        var api = app.MapGroup("/api/v1");

        api.MapGet("/definitions/{kind}", (string kind, IHermesReadStore store) =>
        {
            if (!DefinitionKinds.Contains(kind))
            {
                return Results.NotFound(new { detail = $"Unknown definition type: {kind}" });
            }

            return Results.Ok(store.ListDefinitions(kind));
        });

        api.MapGet("/definitions/{kind}/{definitionId:guid}", (string kind, Guid definitionId, IHermesReadStore store) =>
        {
            if (!DefinitionKinds.Contains(kind))
            {
                return Results.NotFound(new { detail = $"Unknown definition type: {kind}" });
            }

            var definition = store.GetDefinition(kind, definitionId);
            return definition is null ? Results.NotFound(new { detail = "Definition not found" }) : Results.Ok(definition);
        });

        api.MapGet("/definitions/{kind}/{definitionId:guid}/versions", (string kind, Guid definitionId, IHermesReadStore store) =>
        {
            if (!DefinitionKinds.Contains(kind))
            {
                return Results.NotFound(new { detail = $"Unknown definition type: {kind}" });
            }

            return Results.Ok(store.ListDefinitionVersions(kind, definitionId));
        });

        api.MapGet("/pipelines", (IHermesReadStore store) => Results.Ok(store.ListPipelines()));

        api.MapGet("/pipelines/{pipelineId:guid}", (Guid pipelineId, IHermesReadStore store) =>
        {
            var pipeline = store.GetPipeline(pipelineId);
            return pipeline is null ? Results.NotFound(new { detail = "Pipeline not found" }) : Results.Ok(pipeline);
        });

        api.MapGet("/pipelines/{pipelineId:guid}/stages", (Guid pipelineId, IHermesReadStore store) =>
            Results.Ok(store.ListPipelineStages(pipelineId)));

        api.MapGet("/jobs", (IHermesReadStore store, int page = 1, int page_size = 50) =>
            Results.Ok(store.ListJobs(page, page_size)));

        api.MapGet("/jobs/{jobId:guid}", (Guid jobId, IHermesReadStore store) =>
        {
            var job = store.GetJob(jobId);
            return job is null ? Results.NotFound(new { detail = "Job not found" }) : Results.Ok(job);
        });

        api.MapGet("/monitor/stats", (IHermesReadStore store) => Results.Ok(store.GetMonitorStats()));

        api.MapGet("/monitor/activations", (IHermesReadStore store) => Results.Ok(store.ListMonitorActivations()));

        api.MapGet("/monitor/recent-jobs", (IHermesReadStore store, int limit = 20) =>
            Results.Ok(store.ListRecentJobs(limit)));

        return app;
    }
}
