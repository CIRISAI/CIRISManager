const path = require('path');

module.exports = {
  entry: './src/index.ts',
  mode: 'production',
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: 'ts-loader',
        exclude: /node_modules/,
      },
    ],
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.js'],
  },
  output: {
    filename: 'ciristelemetry-sdk.min.js',
    path: path.resolve(__dirname, 'dist'),
    library: {
      name: 'CIRISTelemetry',
      type: 'umd',
      export: 'default'
    },
    globalObject: 'this'
  },
  optimization: {
    minimize: true
  },
  externals: {
    // Don't bundle axios, expect it to be available
    axios: {
      commonjs: 'axios',
      commonjs2: 'axios',
      amd: 'axios',
      root: 'axios'
    }
  }
};