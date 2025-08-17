import axios from 'axios';
import { CIRISManagerClient } from './client';
import { AuthenticationError, NetworkError, CIRISError } from './errors';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('CIRISManagerClient', () => {
  let client: CIRISManagerClient;
  let mockAxiosInstance: any;

  beforeEach(() => {
    mockAxiosInstance = {
      get: jest.fn(),
      post: jest.fn(),
      patch: jest.fn(),
      delete: jest.fn(),
      defaults: {
        headers: {
          common: {}
        }
      },
      interceptors: {
        response: {
          use: jest.fn()
        }
      }
    };

    mockedAxios.create.mockReturnValue(mockAxiosInstance);
    client = new CIRISManagerClient({
      baseURL: 'http://localhost:8888/manager/v1',
      timeout: 5000
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('constructor', () => {
    it('should create axios instance with correct config', () => {
      expect(mockedAxios.create).toHaveBeenCalledWith({
        baseURL: 'http://localhost:8888/manager/v1',
        timeout: 5000,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    });

    it('should add auth token if provided', () => {
      mockedAxios.create.mockClear();
      const client = new CIRISManagerClient({
        token: 'test-token'
      });

      expect(mockedAxios.create).toHaveBeenCalledWith(
        expect.objectContaining({
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer test-token'
          }
        })
      );
    });

    it('should use default baseURL if not provided', () => {
      mockedAxios.create.mockClear();
      const client = new CIRISManagerClient();

      expect(mockedAxios.create).toHaveBeenCalledWith(
        expect.objectContaining({
          baseURL: '/manager/v1'
        })
      );
    });
  });

  describe('setToken', () => {
    it('should update authorization header', () => {
      client.setToken('new-token');
      expect(mockAxiosInstance.defaults.headers.common['Authorization']).toBe('Bearer new-token');
    });
  });

  describe('health', () => {
    it('should call health endpoint', async () => {
      const mockResponse = { data: { status: 'healthy' } };
      mockAxiosInstance.get.mockResolvedValue(mockResponse);

      const result = await client.health();

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/health');
      expect(result).toEqual({ status: 'healthy' });
    });
  });

  describe('status', () => {
    it('should call status endpoint', async () => {
      const mockStatus = {
        status: 'running',
        agents_running: 5,
        agents_total: 10
      };
      mockAxiosInstance.get.mockResolvedValue({ data: mockStatus });

      const result = await client.status();

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/status');
      expect(result).toEqual(mockStatus);
    });
  });

  describe('error handling', () => {
    let errorHandler: (error: any) => Promise<any>;
    let successHandler: (response: any) => any;

    beforeEach(() => {
      // Capture the error handler from interceptor
      const interceptorCall = mockAxiosInstance.interceptors.response.use.mock.calls[0];
      successHandler = interceptorCall[0];
      errorHandler = interceptorCall[1];
    });

    it('should handle 401 errors', async () => {
      const mockOnAuthFailure = jest.fn();
      mockedAxios.create.mockClear();
      
      client = new CIRISManagerClient({
        onAuthFailure: mockOnAuthFailure
      });

      const interceptorCall = mockAxiosInstance.interceptors.response.use.mock.calls[1];
      errorHandler = interceptorCall[1];

      const error = {
        response: { status: 401 }
      };

      await expect(errorHandler(error)).rejects.toThrow(AuthenticationError);
      expect(mockOnAuthFailure).toHaveBeenCalled();
    });

    it('should handle network errors', async () => {
      const error = {
        code: 'ECONNABORTED'
      };

      await expect(errorHandler(error)).rejects.toThrow(NetworkError);
    });

    it('should handle generic errors', async () => {
      const error = {
        response: {
          status: 500,
          data: {
            detail: 'Internal server error'
          }
        }
      };

      await expect(errorHandler(error)).rejects.toThrow(CIRISError);
    });
  });
});