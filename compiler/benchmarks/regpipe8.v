// two-stage registered pipeline: p <= a ^ b; y <= p & c
module regpipe8(clk, a, b, c, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input [7:0] c;
  output reg [7:0] y;
  reg [7:0] p;
  always @(posedge clk) begin
    p <= a ^ b;
    y <= p & c;
  end
endmodule
