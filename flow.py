from metaflow import FlowSpec, step, conda_base

@conda_base(
    libraries={"rich": "12.6.0"},
    python="3.10.4",

)
class MLOpsClubFlow(FlowSpec):

    @step
    def start(self):
        """Every flow DAG must have a function named ``start``."""
        self.var1 = "bogus!"
        self.next(self.step_2)

    @step
    def step_2(self):
        self.var2 = "heinous!"
        self.next(self.end)

    @step
    def end(self):
        """Every flow DAG must have a function named ``end as well``."""
        self.var3 = "most *non* triumphant!"

if __name__ == "__main__":
    MLOpsClubFlow()