# Vespa-app

## Setup
1. Install vespa client following this [guide](https://docs.vespa.ai/en/vespa-cli.html)
2. Set vespa to target cloud `vespa config set target cloud`
3. Deploy
   * `vespa auth login`
   * `vespa config set application groupon.hybridsearch.default`
   * `vespa deploy`