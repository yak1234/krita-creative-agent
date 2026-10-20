kis_add_tests(
    #TestKrita.cpp
    TestChannel.cpp
    TestDocument.cpp
    TestDocumentHistory.cpp
    TestNode.cpp
    TestVectorLayer.cpp
    TestShape.cpp
    TestFilter.cpp
    TestManagedColor.cpp
    TestNotifier.cpp
    TestDocumentChanges.cpp
    TestNotifierChanges.cpp
    TestDocumentRegionRefresh.cpp
    TestDocumentScaledProjection.cpp
    TestKritaAgentResources.cpp
    TestDocumentAgentCraft.cpp
    TestFilterMaskBake.cpp
    TestDocumentFeatures.cpp
    TestNodeAgentTools.cpp
    TestStrokeJobs.cpp
    TestDocumentFeatureBuilders.cpp
    TestLibkisTraps.cpp
    TestLibkisNoView.cpp
    LINK_LIBRARIES kritalibkis kritatestsdk
    )

# Krita Agent: timings for region refresh and the scaled read on a 6000x4500 document (not run by ctest).
krita_add_benchmark(AgentSpeedBenchmark TESTNAME libs-libkis-AgentSpeedBenchmark AgentSpeedBenchmark.cpp)
target_link_libraries(AgentSpeedBenchmark kritalibkis kritatestsdk)

# Krita Agent: timings for Node.paintStrokes() on a 6000x4500 document (task 2.4; not run by ctest).
krita_add_benchmark(AgentStrokeJobsBenchmark TESTNAME libs-libkis-AgentStrokeJobsBenchmark AgentStrokeJobsBenchmark.cpp)
target_link_libraries(AgentStrokeJobsBenchmark kritalibkis kritatestsdk)
