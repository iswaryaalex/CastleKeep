This folder is the one place the agent can write.

It is granted read-write in policy.json as ${workspace}. Everything else on
the machine is, at most, readable - and most of it is not even that.

The scattered files in here are deliberate. Ask Assistant to tidy them up and it
will read them, decide where they belong, and move them. Every one of those
steps is a separate sandbox. Then take ${workspace} out of paths.write, ask
again, and watch the same request fail at the first write.
